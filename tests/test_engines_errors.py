"""A failing `mineru`/`marker` subprocess must surface as a RuntimeError, not
an uncaught subprocess.CalledProcessError - pipeline.py only catches
RuntimeError (and FileNotFoundError/ValueError), so anything else crashes
the whole run and, in --queue mode, aborts every other file in the batch too."""

import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from knowledge_retrieval.engines import marker, mineru


@pytest.fixture
def input_dir_with_pdf(tmp_path) -> Path:
    d = tmp_path / "input"
    d.mkdir()
    (d / "sample.pdf").write_bytes(b"%PDF-1.4\n%%EOF")
    return d


def test_mineru_translates_called_process_error(input_dir_with_pdf, tmp_path):
    with (
        patch("knowledge_retrieval.engines.mineru.shutil.which", return_value="/usr/bin/mineru"),
        patch(
            "knowledge_retrieval.engines.mineru.subprocess.run",
            side_effect=subprocess.CalledProcessError(1, ["mineru"]),
        ),
        pytest.raises(RuntimeError),
    ):
        mineru.convert(input_dir_with_pdf, tmp_path / "output", 1, [])


def test_marker_translates_called_process_error(input_dir_with_pdf, tmp_path):
    with (
        patch("knowledge_retrieval.engines.marker.shutil.which", return_value="/usr/bin/marker"),
        patch(
            "knowledge_retrieval.engines.marker.subprocess.run",
            side_effect=subprocess.CalledProcessError(1, ["marker"]),
        ),
        pytest.raises(RuntimeError),
    ):
        marker.convert(input_dir_with_pdf, tmp_path / "output", 1, [])
