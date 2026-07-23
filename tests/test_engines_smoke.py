"""Smoke test: convert a small sample PDF through each conversion engine and
confirm it produces non-empty Markdown output somewhere under the output
directory. Does not assert on exact content - model output differs per
engine/version, and isn't stable enough to pin down.

Each engine is skipped (not failed) when its dependency isn't installed, so
this passes on a machine that only installed a subset of engine extras.
"""

import importlib.util
import shutil
from pathlib import Path

import pytest
from reportlab.lib.pagesizes import LETTER
from reportlab.pdfgen import canvas

from knowledge_retrieval.engines import ENGINES

pytestmark = pytest.mark.slow


def _make_sample_pdf(path: Path) -> None:
    """Generate a minimal one-page PDF with real rendered text at `path`."""
    c = canvas.Canvas(str(path), pagesize=LETTER)
    c.drawString(72, 720, "1. Scope")
    c.drawString(72, 690, "This is a smoke-test document for PDF-to-Markdown conversion.")
    c.drawString(72, 660, "It exercises the pipeline end to end for each engine.")
    c.save()


@pytest.fixture(scope="module")
def sample_input_dir(tmp_path_factory) -> Path:
    """A directory containing one sample PDF, shared across all engine tests."""
    input_dir = tmp_path_factory.mktemp("engine_smoke_input")
    _make_sample_pdf(input_dir / "sample.pdf")
    return input_dir


def _engine_available(engine_name: str) -> bool:
    """Check whether the given engine's dependency is installed."""
    if engine_name in ("marker", "mineru"):
        return shutil.which(engine_name) is not None
    if engine_name == "paddleocr":
        return importlib.util.find_spec("paddleocr") is not None
    return False


def _collect_markdown(output_dir: Path) -> str:
    """Concatenate the text of every Markdown file found under output_dir."""
    return "\n".join(
        md_file.read_text(encoding="utf-8") for md_file in output_dir.rglob("*.md")
    )


@pytest.mark.parametrize("engine_name", ["marker", "mineru", "paddleocr"])
def test_engine_produces_nonempty_markdown(  # pylint: disable=redefined-outer-name
    engine_name, sample_input_dir, tmp_path
):
    """Each engine should convert the sample PDF into non-empty Markdown.

    `sample_input_dir` here is pytest's fixture-injection mechanism, not a
    real name collision with the fixture function defined above.
    """
    if not _engine_available(engine_name):
        pytest.skip(f"'{engine_name}' engine is not installed")

    output_dir = tmp_path / "output"
    convert = ENGINES[engine_name]
    convert(sample_input_dir, output_dir, 1, [])

    markdown = _collect_markdown(output_dir)
    assert markdown.strip(), f"{engine_name} produced no markdown output"
