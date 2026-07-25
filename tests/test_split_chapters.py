"""Tests for chapter splitting, including the automatic sub-splitting of
chapters longer than --max-pages into roughly-equal, max-size parts."""

from pathlib import Path

from pypdf import PdfReader, PdfWriter

from knowledge_retrieval.split_chapters import Chapter, compute_page_chunks, write_chapters


def test_compute_page_chunks_under_threshold_is_unsplit():
    assert compute_page_chunks(20, max_pages=30) == [20]
    assert compute_page_chunks(30, max_pages=30) == [30]


def test_compute_page_chunks_35_pages_splits_18_17():
    assert compute_page_chunks(35, max_pages=30) == [18, 17]


def test_compute_page_chunks_98_pages_splits_25_25_25_23():
    assert compute_page_chunks(98, max_pages=30) == [25, 25, 25, 23]


def _make_pdf(path: Path, page_count: int) -> None:
    writer = PdfWriter()
    for _ in range(page_count):
        writer.add_blank_page(width=200, height=200)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "wb") as f:
        writer.write(f)


def test_write_chapters_splits_oversized_chapter_into_parts(tmp_path):
    src = tmp_path / "source.pdf"
    _make_pdf(src, page_count=98)
    reader = PdfReader(str(src))

    ranges = [(Chapter(title="Chapter A", start_page=0), 0, 98)]
    output_dir = tmp_path / "out"
    write_chapters(reader, ranges, output_dir, max_pages=30)

    files = sorted(output_dir.glob("*.pdf"))
    names = [p.name for p in files]
    assert names == [
        "01_Chapter_A_01.pdf",
        "01_Chapter_A_02.pdf",
        "01_Chapter_A_03.pdf",
        "01_Chapter_A_04.pdf",
    ]

    page_counts = [len(PdfReader(str(p)).pages) for p in files]
    assert page_counts == [25, 25, 25, 23]


def test_write_chapters_leaves_short_chapter_unsplit(tmp_path):
    src = tmp_path / "source.pdf"
    _make_pdf(src, page_count=10)
    reader = PdfReader(str(src))

    ranges = [(Chapter(title="Chapter B", start_page=0), 0, 10)]
    output_dir = tmp_path / "out"
    write_chapters(reader, ranges, output_dir, max_pages=30)

    files = list(output_dir.glob("*.pdf"))
    assert [p.name for p in files] == ["01_Chapter_B.pdf"]
    assert len(PdfReader(str(files[0])).pages) == 10
