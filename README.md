# knowledge-retrieval

Split PDFs into per-chapter files and convert them to Markdown, ready for downstream
retrieval/RAG pipelines. Conversion is pluggable — [marker](https://github.com/datalab-to/marker)
is the default engine, [docling](https://github.com/docling-project/docling) is also supported.

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
pip install -e .
```

`requirements.txt` installs both engines (`marker-pdf` and `docling`). If you only want
the default `marker` engine, `pip install -e .` alone is enough; add the `docling` engine
with `pip install -e ".[docling]"`.

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
knowledge-retrieval input.pdf --workers 8             # more parallelism
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

## Engines

| Engine    | Package      | Concurrency knob        |
|-----------|--------------|--------------------------|
| `marker`  | `marker-pdf` | `--workers` (default 1)  |
| `docling` | `docling`    | `--num-threads` (default 1) |

Select the engine with `--engine {marker,docling}` on `knowledge-retrieval`. Both engines
run as subprocesses of their own CLI, so any of their own flags can be passed through
after a `--` separator.

## Project layout

```
knowledge-retrieval/
├── src/knowledge_retrieval/
│   ├── pipeline.py          # unified split+convert CLI
│   ├── split_chapters.py    # chapter splitting (bookmarks / heading heuristic)
│   ├── extract.py           # page-range extraction
│   └── engines/             # marker / docling CLI wrappers
├── references/               # source PDFs + split chapters (gitignored)
├── outputs/                  # converted Markdown (gitignored)
├── requirements.txt
└── pyproject.toml
```

`references/` and `outputs/` are excluded from version control since they hold local
source documents and generated files.
