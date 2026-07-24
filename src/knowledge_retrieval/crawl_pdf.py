"""PDF branch of the batch crawl pipeline. When a target URL points directly
at a PDF (see `crawl_router.is_pdf_url`), it's downloaded and handed off to
this repo's own PDF engines (mineru / marker / paddleocr) instead of being
scraped as a web page - no chapter splitting, since a scraped PDF is
typically a standalone document rather than a book.
"""

import tempfile
import urllib.request
from pathlib import Path

from knowledge_retrieval.engines import DEFAULT_ENGINE, get_engine
from knowledge_retrieval.pipeline import single_file_dir


def download_pdf(url: str, dest: Path, timeout: float = 60.0) -> None:
    """Download the PDF at `url` to `dest`."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    request = urllib.request.Request(url, headers={"User-Agent": "knowledge-retrieval-crawl"})
    with urllib.request.urlopen(request, timeout=timeout) as response, open(dest, "wb") as f:  # nosec B310 - url comes from the caller's own input list
        f.write(response.read())


def handle_pdf_url(url: str, name: str, output_dir: Path, engine_name: str = DEFAULT_ENGINE) -> Path:
    """Download the PDF at `url` and convert it to Markdown via `engine_name`.

    `name` is used as the PDF's stem (typically a slug derived from the URL),
    so the converted output lands at `output_dir/<name>/<name>.md`. Returns
    that document directory.
    """
    convert = get_engine(engine_name)
    with tempfile.TemporaryDirectory() as tmp:
        pdf_path = Path(tmp) / f"{name}.pdf"
        download_pdf(url, pdf_path)
        with single_file_dir(pdf_path) as tmp_dir:
            convert(tmp_dir, output_dir, 1, [])
    return output_dir / name
