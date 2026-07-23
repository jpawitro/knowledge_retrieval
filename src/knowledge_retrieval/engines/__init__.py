"""Registry of PDF-to-Markdown conversion engines.

Each engine module exposes a `convert(input_dir, output_dir, workers, extra_args)`
function that shells out to that engine's own batch-conversion CLI.
"""

from . import marker, mineru, paddleocr

ENGINES = {
    "mineru": mineru.convert,
    "marker": marker.convert,
    "paddleocr": paddleocr.convert,
}

DEFAULT_ENGINE = "mineru"


def get_engine(name: str):
    """Look up a registered engine's `convert` function by name."""
    try:
        return ENGINES[name]
    except KeyError:
        raise ValueError(
            f"Unknown engine '{name}'. Available engines: {', '.join(sorted(ENGINES))}"
        ) from None
