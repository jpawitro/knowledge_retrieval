"""Tests for the resume/skip-already-converted behavior in the unified
split+convert CLI (knowledge_retrieval.pipeline)."""

from pathlib import Path

import pytest

from knowledge_retrieval import pipeline


def _touch_pdf(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"%PDF-1.4 fake")


def _mark_converted(output_dir: Path, stem: str) -> None:
    doc_dir = output_dir / stem
    doc_dir.mkdir(parents=True, exist_ok=True)
    (doc_dir / f"{stem}.md").write_text("already converted", encoding="utf-8")


def test_is_already_converted(tmp_path):
    output_dir = tmp_path / "outputs" / "doc"
    assert not pipeline.is_already_converted(output_dir, "01_chapter")

    _mark_converted(output_dir, "01_chapter")
    assert pipeline.is_already_converted(output_dir, "01_chapter")


def test_is_already_converted_nested_backend_subdir(tmp_path):
    """mineru output produced before its flatten-the-subdir step existed (or
    any engine that nests output under its own backend/method subdir) leaves
    <stem>/<backend>/<stem>.md instead of the flattened <stem>/<stem>.md -
    this shape shows up in real converted-output folders and must still
    count as already converted."""
    output_dir = tmp_path / "outputs" / "doc"
    nested = output_dir / "01_chapter" / "hybrid_auto"
    nested.mkdir(parents=True)
    (nested / "01_chapter.md").write_text("nested output", encoding="utf-8")

    assert pipeline.is_already_converted(output_dir, "01_chapter")


def test_subset_dir_contains_only_given_files(tmp_path):
    a = tmp_path / "a.pdf"
    b = tmp_path / "b.pdf"
    _touch_pdf(a)
    _touch_pdf(b)

    with pipeline.subset_dir([a]) as scratch:
        names = {p.name for p in scratch.glob("*.pdf")}
        assert names == {"a.pdf"}


class _FakeConvert:
    """Records the set of PDF filenames it was asked to convert and drops a
    <stem>/<stem>.md marker for each, mimicking a real engine's output shape."""

    def __init__(self):
        self.calls: list[set[str]] = []

    def __call__(self, input_dir, output_dir, workers, extra_args):  # pylint: disable=unused-argument
        pdfs = sorted(p.name for p in Path(input_dir).glob("*.pdf"))
        self.calls.append(set(pdfs))
        for pdf in Path(input_dir).glob("*.pdf"):
            _mark_converted(Path(output_dir), pdf.stem)


@pytest.fixture
def fake_convert(monkeypatch):
    fake = _FakeConvert()
    monkeypatch.setattr(pipeline, "get_engine", lambda name: fake)
    return fake


def test_main_skips_already_converted_chapters(  # pylint: disable=redefined-outer-name
    tmp_path, monkeypatch, fake_convert
):
    references_dir = tmp_path / "references"
    outputs_dir = tmp_path / "outputs"
    name = "doc"
    split_dir = references_dir / name

    _touch_pdf(split_dir / "01_intro.pdf")
    _touch_pdf(split_dir / "02_body.pdf")
    _mark_converted(outputs_dir / name, "01_intro")  # already done

    monkeypatch.setattr(
        "sys.argv",
        [
            "knowledge-retrieval",
            str(split_dir / "01_intro.pdf"),  # input is unused once --skip-split+--references-dir apply
            "--name", name,
            "--references-dir", str(references_dir),
            "--outputs-dir", str(outputs_dir),
            "--skip-split",
        ],
    )

    pipeline.main()

    assert fake_convert.calls == [{"02_body.pdf"}]
    assert pipeline.is_already_converted(outputs_dir / name, "02_body")


def test_main_force_reconverts_everything(  # pylint: disable=redefined-outer-name
    tmp_path, monkeypatch, fake_convert
):
    references_dir = tmp_path / "references"
    outputs_dir = tmp_path / "outputs"
    name = "doc"
    split_dir = references_dir / name

    _touch_pdf(split_dir / "01_intro.pdf")
    _touch_pdf(split_dir / "02_body.pdf")
    _mark_converted(outputs_dir / name, "01_intro")

    monkeypatch.setattr(
        "sys.argv",
        [
            "knowledge-retrieval",
            str(split_dir / "01_intro.pdf"),
            "--name", name,
            "--references-dir", str(references_dir),
            "--outputs-dir", str(outputs_dir),
            "--skip-split",
            "--force",
        ],
    )

    pipeline.main()

    assert fake_convert.calls == [{"01_intro.pdf", "02_body.pdf"}]


def test_main_reports_nothing_to_do_when_all_converted(  # pylint: disable=redefined-outer-name
    tmp_path, monkeypatch, fake_convert
):
    references_dir = tmp_path / "references"
    outputs_dir = tmp_path / "outputs"
    name = "doc"
    split_dir = references_dir / name

    _touch_pdf(split_dir / "01_intro.pdf")
    _mark_converted(outputs_dir / name, "01_intro")

    monkeypatch.setattr(
        "sys.argv",
        [
            "knowledge-retrieval",
            str(split_dir / "01_intro.pdf"),
            "--name", name,
            "--references-dir", str(references_dir),
            "--outputs-dir", str(outputs_dir),
            "--skip-split",
        ],
    )

    pipeline.main()

    assert fake_convert.calls == []
