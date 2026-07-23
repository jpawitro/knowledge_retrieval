# knowledge-retrieval

Split PDFs into per-chapter files and convert them to Markdown, ready for downstream
retrieval/RAG pipelines. Conversion is pluggable — [MinerU](https://github.com/opendatalab/MinerU)
is the default engine; [marker](https://github.com/datalab-to/marker) and
[PaddleOCR](https://github.com/PaddlePaddle/PaddleOCR) (PP-StructureV3) are also supported,
in that priority order (mineru, then marker, then paddleocr).
Every engine is an optional extra — no conversion engine is installed by default, so you
only pull in the one(s) you actually need. This matters if you can't install marker at all
(e.g. its license terms) since `mineru` and `paddleocr` work as a complete, marker-free install.

## Tools

- **`knowledge-retrieval`** — the main pipeline: split a PDF into chapters, then convert
  each chapter to Markdown, in one command.
- **`knowledge-retrieval-split`** — split a PDF into one file per chapter only (embedded
  bookmarks if present, else a heading-detection heuristic).
- **`knowledge-retrieval-extract`** — extract an arbitrary page range/subset from a PDF
  into a new PDF file.

## Installation

Requires [uv](https://docs.astral.sh/uv/). `uv sync` creates `.venv` and installs
everything on its own - no manual venv setup needed.

```bash
uv sync --extra mineru          # or marker / paddleocr, see below
```

A bare `uv sync` installs no conversion engine at all - the base package only pulls in
`pypdf`. Each engine is its own extra, so you can install exactly the ones you need and
nothing else:

```bash
uv sync --extra mineru                       # mineru[core]
uv sync --extra marker                       # marker-pdf
uv sync --extra paddleocr                    # paddleocr[doc-parser] + paddlepaddle
uv sync --extra mineru --extra paddleocr     # any combination, e.g. everything except marker
```

This is the setup to use if you can't install `marker` at all (its license terms, for
example): `mineru` and `paddleocr` have no dependency on marker or on each other, so
`uv sync --extra mineru --extra paddleocr` gives you a complete, marker-free install.

Run commands with `uv run`, e.g. `uv run knowledge-retrieval input.pdf` - no need to
activate the venv yourself. Conversion engines download their own model weights on first
use (to `~/.cache/huggingface` and, for paddleocr, `~/.paddlex`), so the first run of each
engine will be slower while weights download.

## Usage

### Full pipeline: split + convert

```bash
uv run knowledge-retrieval references/tb880.pdf
```

This:

1. Splits `tb880.pdf` into chapters (auto-detected via bookmarks, falling back to a
   heading heuristic) and writes them to `references/tb880/`.
2. Converts each chapter PDF in `references/tb880/` to Markdown using the `mineru`
   engine (default 1 worker) and writes the results to `outputs/tb880/`.

The output folder name is derived from the input file's stem by default (`tb880.pdf` ->
`tb880/`), so split PDFs and their converted Markdown always land in matching
`references/<name>/` and `outputs/<name>/` folders.

Common options:

```bash
uv run knowledge-retrieval input.pdf --engine marker         # use marker instead of mineru
uv run knowledge-retrieval input.pdf --engine paddleocr      # use paddleocr (PP-StructureV3) instead of mineru
uv run knowledge-retrieval input.pdf --workers 8             # more parallelism (opt-in; see Engines below)
uv run knowledge-retrieval input.pdf --name tb880            # override the output folder name
uv run knowledge-retrieval input.pdf --split-mode headings   # force heading-detection over bookmarks
uv run knowledge-retrieval input.pdf --skip-split            # convert an already-split references/<name>/
uv run knowledge-retrieval input.pdf -- --disable_image_extraction  # pass extra args through to the engine's own CLI
```

Run `uv run knowledge-retrieval -h` for the full option list.

### Split only

```bash
uv run knowledge-retrieval-split input.pdf -o chapters/                  # auto: bookmarks, else heuristic
uv run knowledge-retrieval-split input.pdf -o chapters/ --mode bookmarks  # force bookmarks only
uv run knowledge-retrieval-split input.pdf -o chapters/ --mode headings   # force heading-detection
uv run knowledge-retrieval-split input.pdf --list                         # just list chapters, write nothing
```

Run `uv run knowledge-retrieval-split -h` for the full option list.

### Extract a page range

```bash
uv run knowledge-retrieval-extract input.pdf -p 3-7 -o out.pdf
uv run knowledge-retrieval-extract input.pdf -p 1,4,9 -o out.pdf
uv run knowledge-retrieval-extract input.pdf -p 1-3,7,10-12 -o out.pdf
```

Run `uv run knowledge-retrieval-extract -h` for the full option list.

### Tests

```bash
uv sync --extra mineru --extra paddleocr --extra test   # or "--extra marker" - see note below
uv run pytest
```

`tests/test_engines_smoke.py` runs `marker`, `mineru`, and `paddleocr` end to end on a
generated one-page sample PDF and checks each produces non-empty Markdown output (no
assertions on exact content, since model output differs per engine/version). Engines
whose extra isn't installed are skipped, not failed. These tests load real models on
first run, so expect a slow first pass while weights download.

**`marker` and `mineru` can't be installed together.** `marker-pdf` pins `pillow<11.0.0`
and `mineru` requires `pillow>=11.0.0` - no released version of either package resolves
this, so the two extras are mutually exclusive in the same environment. `pyproject.toml`
declares this via `tool.uv.conflicts`, so `uv sync --extra marker --extra mineru` (and
`uv sync --all-extras`) fail fast with a clear error instead of an opaque resolver
backtrace. If you need to test both engines, use two separate environments (e.g. two
`uv sync --extra ...` venvs) and run the smoke tests against each.

## Engines

| Engine       | Extra           | Package(s)                              | LaTeX formulas | `--workers` behavior |
|--------------|-----------------|------------------------------------------|----------------|-----------------------|
| `mineru`     | `[mineru]`      | `mineru[core]`                             | yes            | no native flag: `--workers 1` (default) runs one `mineru` process over the whole batch; `--workers N>1` shards files across N parallel `mineru` processes |
| `marker`     | `[marker]`      | `marker-pdf`                              | yes            | native CLI flag |
| `paddleocr`  | `[paddleocr]`   | `paddleocr[doc-parser]` + `paddlepaddle`   | yes (PP-FormulaNet, via PP-StructureV3) | runs in-process, not a CLI subprocess: `--workers 1` (default) loads one PP-StructureV3 model stack and processes files sequentially; `--workers N>1` runs N processes each with their own model stack |

Select the engine with `--engine {mineru,marker,paddleocr}` on `knowledge-retrieval`.

**`--workers` default is 1 for every engine, deliberately.** Each worker loads a full model
stack independently, so more workers means more memory pressure, not necessarily more
throughput - on a memory-constrained machine, `--workers 4` can end up *slower* than
sequential. Only raise it if you've confirmed your machine has the headroom.

`marker` and `mineru` run as subprocesses of their own CLI, so any of their own flags can
be passed through after a `--` separator. `paddleocr` runs PP-StructureV3 in-process
(needed to correctly merge multi-page PDF output - see `engines/paddleocr.py`), so it does
not accept passthrough CLI args.

## Project layout

```
knowledge-retrieval/
├── src/knowledge_retrieval/
│   ├── pipeline.py          # unified split+convert CLI
│   ├── split_chapters.py    # chapter splitting (bookmarks / heading heuristic)
│   ├── extract.py           # page-range extraction
│   └── engines/             # mineru / marker / paddleocr wrappers
├── references/               # source PDFs + split chapters (gitignored)
├── outputs/                  # converted Markdown (gitignored)
├── tests/                     # smoke tests
└── pyproject.toml
```

`references/` and `outputs/` are excluded from version control since they hold local
source documents and generated files.
