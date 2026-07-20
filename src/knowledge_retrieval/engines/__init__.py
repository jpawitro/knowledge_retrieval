"""Registry of PDF-to-Markdown conversion engines.

Each engine module exposes a `convert(input_dir, output_dir, workers, extra_args)`
function that shells out to that engine's own batch-conversion CLI.
"""

from . import docling, marker

ENGINES = {
    "marker": marker.convert,
    "docling": docling.convert,
}

DEFAULT_ENGINE = "marker"


def get_engine(name: str):
    try:
        return ENGINES[name]
    except KeyError:
        raise ValueError(
            f"Unknown engine '{name}'. Available engines: {', '.join(sorted(ENGINES))}"
        ) from None
