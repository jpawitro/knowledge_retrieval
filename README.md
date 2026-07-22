# knowledge-retrieval

Split PDFs into per-chapter files and convert them to Markdown, ready for downstream
retrieval/RAG pipelines. Conversion is pluggable — [marker](https://github.com/datalab-to/marker)
is the default engine; [docling](https://github.com/docling-project/docling),
[MinerU](https://github.com/opendatalab/MinerU), and
[PaddleOCR](https://github.com/PaddlePaddle/PaddleOCR) (PP-StructureV3) are also supported.
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

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pip install -e ".[marker]"          # or docling / mineru / paddleocr, see below
```

`pip install -e .` alone installs no conversion engine at all - `requirements.txt` and the
base package only pull in `pypdf`. Each engine is its own extra, so you can install exactly
the ones you need and nothing else:

```bash
pip install -e ".[marker]"          # marker-pdf
pip install -e ".[docling]"         # docling
pip install -e ".[mineru]"          # mineru[core]
pip install -e ".[paddleocr]"       # paddleocr[doc-parser] + paddlepaddle
pip install -e ".[docling,mineru,paddleocr]"   # any combination, e.g. everything except marker
```

This is the setup to use if you can't install `marker` at all (its license terms, for
example): `mineru` and `paddleocr` have no dependency on marker or on each other, so
`pip install -e ".[mineru,paddleocr]"` gives you a complete, marker-free install.

## Usage

### Full pipeline: split + convert

```bash
knowledge-retrieval references/tb880.pdf
```

This:

1. Splits `tb880.pdf` into chapters (auto-detected via bookmarks, falling back to a
   heading heuristic) and writes them to `references/tb880/`.
2. Converts each chapter PDF in `references/tb880/` to Markdown using the `marker`
   engine (default 1 worker) and writes the results to `outputs/tb880/`.

The output folder name is derived from the input file's stem by default (`tb880.pdf` ->
`tb880/`), so split PDFs and their converted Markdown always land in matching
`references/<name>/` and `outputs/<name>/` folders.

Common options:

```bash
knowledge-retrieval input.pdf --engine docling        # use docling instead of marker
knowledge-retrieval input.pdf --engine mineru         # use mineru instead of marker
knowledge-retrieval input.pdf --engine paddleocr      # use paddleocr (PP-StructureV3) instead of marker
knowledge-retrieval input.pdf --workers 8             # more parallelism (opt-in; see Engines below)
knowledge-retrieval input.pdf --name tb880            # override the output folder name
knowledge-retrieval input.pdf --split-mode headings   # force heading-detection over bookmarks
knowledge-retrieval input.pdf --skip-split            # convert an already-split references/<name>/
knowledge-retrieval input.pdf -- --disable_image_extraction  # pass extra args through to the engine's own CLI
```

Run `knowledge-retrieval -h` for the full option list.

### Split only

```bash
knowledge-retrieval-split input.pdf -o chapters/                  # auto: bookmarks, else heuristic
knowledge-retrieval-split input.pdf -o chapters/ --mode bookmarks  # force bookmarks only
knowledge-retrieval-split input.pdf -o chapters/ --mode headings   # force heading-detection
knowledge-retrieval-split input.pdf --list                         # just list chapters, write nothing
```

Run `knowledge-retrieval-split -h` for the full option list.

### Extract a page range

```bash
knowledge-retrieval-extract input.pdf -p 3-7 -o out.pdf
knowledge-retrieval-extract input.pdf -p 1,4,9 -o out.pdf
knowledge-retrieval-extract input.pdf -p 1-3,7,10-12 -o out.pdf
```

Run `knowledge-retrieval-extract -h` for the full option list.

### Tests

```bash
pip install -e ".[marker,mineru,paddleocr,test]"
pytest
```

`tests/test_engines_smoke.py` runs `marker`, `mineru`, and `paddleocr` end to end on a
generated one-page sample PDF and checks each produces non-empty Markdown output (no
assertions on exact content, since model output differs per engine/version). Engines
whose extra isn't installed are skipped, not failed. These tests load real models on
first run, so expect a slow first pass while weights download.

## Engines

| Engine       | Extra           | Package(s)                              | LaTeX formulas | `--workers` behavior |
|--------------|-----------------|------------------------------------------|----------------|-----------------------|
| `marker`     | `[marker]`      | `marker-pdf`                              | yes            | native CLI flag |
| `docling`    | `[docling]`     | `docling`                                  | partial        | native CLI flag (`--num-threads`) |
| `mineru`     | `[mineru]`      | `mineru[core]`                             | yes            | no native flag: `--workers 1` (default) runs one `mineru` process over the whole batch; `--workers N>1` shards files across N parallel `mineru` processes |
| `paddleocr`  | `[paddleocr]`   | `paddleocr[doc-parser]` + `paddlepaddle`   | yes (PP-FormulaNet, via PP-StructureV3) | runs in-process, not a CLI subprocess: `--workers 1` (default) loads one PP-StructureV3 model stack and processes files sequentially; `--workers N>1` runs N processes each with their own model stack |

Select the engine with `--engine {marker,docling,mineru,paddleocr}` on `knowledge-retrieval`.

**`--workers` default is 1 for every engine, deliberately.** Each worker loads a full model
stack independently, so more workers means more memory pressure, not necessarily more
throughput - on a memory-constrained machine, `--workers 4` can end up *slower* than
sequential. Only raise it if you've confirmed your machine has the headroom.

`marker` and `docling` run as subprocesses of their own CLI, so any of their own flags can
be passed through after a `--` separator; the same is true for `mineru`. `paddleocr` runs
PP-StructureV3 in-process (needed to correctly merge multi-page PDF output - see
`engines/paddleocr.py`), so it does not accept passthrough CLI args.

## Project layout

```
knowledge-retrieval/
├── src/knowledge_retrieval/
│   ├── pipeline.py          # unified split+convert CLI
│   ├── split_chapters.py    # chapter splitting (bookmarks / heading heuristic)
│   ├── extract.py           # page-range extraction
│   └── engines/             # marker / docling / mineru / paddleocr wrappers
├── references/               # source PDFs + split chapters (gitignored)
├── outputs/                  # converted Markdown (gitignored)
├── tests/                     # smoke tests
├── requirements.txt
└── pyproject.toml
```

`references/` and `outputs/` are excluded from version control since they hold local
source documents and generated files.
