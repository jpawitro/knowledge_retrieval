# knowledge-retrieval

Turn PDFs and web pages into Markdown, ready for downstream retrieval/RAG pipelines.
Conversion is pluggable in both directions:

- **PDFs**: split into per-chapter files, then convert each to Markdown via
  [MinerU](https://github.com/opendatalab/MinerU) (default), [marker](https://github.com/datalab-to/marker),
  or [PaddleOCR](https://github.com/PaddlePaddle/PaddleOCR) (PP-StructureV3).
- **Web pages**: scrape a URL to Markdown via [Crawl4AI](https://github.com/unclecode/crawl4ai) +
  [Trafilatura](https://github.com/adbar/trafilatura) (default) or [Firecrawl](https://firecrawl.dev)
  (hosted API).

Every engine is an optional extra — nothing is installed by default, so you only pull in
the one(s) you actually need. This matters if you can't install marker at all (e.g. its
license terms) since `mineru` and `paddleocr` work as a complete, marker-free install.

## Tools

- **`knowledge-retrieval`** — the main PDF pipeline: split a PDF into chapters, then
  convert each chapter to Markdown, in one command.
- **`knowledge-retrieval-split`** — split a PDF into one file per chapter only (embedded
  bookmarks if present, else a heading-detection heuristic).
- **`knowledge-retrieval-extract`** — extract an arbitrary page range/subset from a PDF
  into a new PDF file.
- **`knowledge-retrieval-web`** — scrape a single URL to a Markdown file.
- **`knowledge-retrieval-crawl`** — batch-scrape a list of URLs, with automatic
  Crawl4AI → Firecrawl fallback, PDF hand-off, and recrawl dedup. See
  [Batch web crawling](#batch-web-crawling).

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
uv sync --extra crawl4ai                     # crawl4ai + trafilatura
uv sync --extra firecrawl                    # firecrawl-py
uv sync --extra mineru --extra paddleocr     # any combination, e.g. everything except marker
```

This is the setup to use if you can't install `marker` at all (its license terms, for
example): `mineru` and `paddleocr` have no dependency on marker or on each other, so
`uv sync --extra mineru --extra paddleocr` gives you a complete, marker-free install.

Run commands with `uv run`, e.g. `uv run knowledge-retrieval input.pdf` - no need to
activate the venv yourself. Conversion engines download their own model weights on first
use (to `~/.cache/huggingface` and, for paddleocr, `~/.paddlex`), so the first run of each
engine will be slower while weights download.

`crawl4ai` drives a real headless Chromium via Playwright, so after installing that extra
you also need to download its browser binaries once:

```bash
uv sync --extra crawl4ai
uv run crawl4ai-setup
```

`firecrawl` needs an API key. Copy `.env.example` to `.env` and fill in
`FIRECRAWL_API_KEY` - both `knowledge-retrieval-web` and `knowledge-retrieval-crawl` load
`.env` automatically via `python-dotenv`. `.env` is gitignored; never commit real keys.

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

Any chapter longer than 30 pages is automatically divided into roughly-equal, max-size
sub-parts, since some conversion engines slow down or lose accuracy on very long inputs:
a 35-page chapter becomes two files (18 + 17 pages), a 98-page chapter becomes four (25 +
25 + 25 + 23 pages), etc. Sub-parts are named with a `_NN` suffix, e.g.
`04_Cable_Losses_Overview_01.pdf`, `04_Cable_Losses_Overview_02.pdf`. Pass `--max-pages`
to change the threshold (or set it very high to effectively disable sub-splitting).

Chapters already converted are skipped automatically: before converting, each chapter
PDF is checked against `outputs/<name>/<chapter-stem>/<chapter-stem>.md`, and any that
already exist are left alone. This makes it safe to re-run the same command to pick up
where a previous run crashed or was interrupted, or to batch-convert a folder of
already-split references a few PDFs at a time. Pass `--force` to reconvert everything
regardless of what's already in `outputs/`.

Common options:

```bash
uv run knowledge-retrieval input.pdf --engine marker         # use marker instead of mineru
uv run knowledge-retrieval input.pdf --engine paddleocr      # use paddleocr (PP-StructureV3) instead of mineru
uv run knowledge-retrieval input.pdf --workers 8             # more parallelism (opt-in; see Engines below)
uv run knowledge-retrieval input.pdf --name tb880            # override the output folder name
uv run knowledge-retrieval input.pdf --mode headings         # force heading-detection over bookmarks
uv run knowledge-retrieval input.pdf --max-pages 50           # allow chapters up to 50 pages before sub-splitting
uv run knowledge-retrieval input.pdf --skip-split            # convert an already-split references/<name>/
uv run knowledge-retrieval input.pdf --force                 # reconvert even chapters already in outputs/<name>/
uv run knowledge-retrieval input.pdf -- --disable_image_extraction  # pass extra args through to the engine's own CLI
```

Run `uv run knowledge-retrieval -h` for the full option list.

#### Batch mode: a YAML queue

Pass `--queue queue.yaml` instead of a positional input to split and convert several
PDFs in one run. It's the same queue file format as `knowledge-retrieval-split`'s
`--queue` (see below), plus pipeline-only per-file/`defaults` keys: `name`,
`references_dir`, `outputs_dir`, `engine`, `workers`, `skip_split`, `force`, and
`engine_args` (a list, standing in for the trailing `-- ...` engine args).

```yaml
# queue.yaml
defaults:
  outputs_dir: outputs
  engine: mineru

files:
  - path: /path/to/book1.pdf
    chapters:                     # manual page ranges - skips detection entirely
      - chapter 1, 1-10
      - chapter 2, 11-20

  - path: /path/to/book2.pdf       # no `chapters`: falls back to bookmark/heading detection
    bookmark_level: 1              # per-file override of defaults/CLI (wins over both)
    engine: marker                 # can override the engine per file too
```

```bash
uv run knowledge-retrieval --queue queue.yaml
```

#### Batch mode: a folder of PDFs

Pass `--folder path/to/folder` instead of a positional input to split and convert every
`*.pdf` directly inside that folder, one at a time, using the same options (`--engine`,
`--mode`, `--workers`, etc.) for each file. Each file's output folder name comes from its
own stem, so `--name` isn't allowed with `--folder`.

```bash
uv run knowledge-retrieval --folder path/to/folder
uv run knowledge-retrieval --folder path/to/folder --engine marker --workers 8
```

This is a simpler alternative to `--queue` when every file should use identical options -
use `--queue` instead when different files need different settings (e.g. manual chapter
ranges or a different engine per file).

### Split only

```bash
uv run knowledge-retrieval-split input.pdf -o chapters/                  # auto: bookmarks, else heuristic
uv run knowledge-retrieval-split input.pdf -o chapters/ --mode bookmarks  # force bookmarks only
uv run knowledge-retrieval-split input.pdf -o chapters/ --mode headings   # force heading-detection
uv run knowledge-retrieval-split input.pdf -o chapters/ --max-pages 50    # allow chapters up to 50 pages before sub-splitting
uv run knowledge-retrieval-split input.pdf -o chapters/ --bookmark-level 1  # chapters are the 2nd-level bookmarks
uv run knowledge-retrieval-split input.pdf --list                         # just list chapters, write nothing
```

`-o/--output-dir` is a *parent* directory: chapters land in `<output-dir>/<input-stem>/`,
e.g. `input.pdf` with `-o chapters/` writes to `chapters/input/` - matching
`knowledge-retrieval`'s `references_dir`/`outputs_dir` convention of nesting each
document's output under its own `<name>/` subfolder.

Chapters over 30 pages (by default) are automatically divided into roughly-equal,
max-size sub-parts named with a `_NN` suffix - see [Full pipeline](#full-pipeline-split--convert)
above for details.

Some PDFs' outline entries aren't all at the same conceptual level, or mix in
non-chapter entries alongside real ones:

- `--bookmark-level N` picks one exact nesting level as the chapters (0 =
  top-level, the default; 1 = second-level, etc.) - useful when, e.g., the
  top-level bookmarks are just container/file wrappers and the real sections
  live one level deeper.
- `--exclude-title REGEX` (case-insensitive) drops any bookmark at that level
  whose title matches - e.g. `--exclude-title '^(Figures|Tables)$'` for
  outlines that mix in a non-hierarchical "Figures"/"Tables" grouping
  bookmark alongside the real chapters.

Run `uv run knowledge-retrieval-split -h` for the full option list.

#### Batch mode: a YAML queue

Pass `--queue queue.yaml` instead of a positional input to split several PDFs
in one run, optionally with manually-specified chapter page ranges per file
(bypassing bookmark/heading detection entirely for that file). Manual
chapters still go through the same `--max-pages` sub-splitting as detected
ones.

```yaml
# queue.yaml
defaults:               # applied to every file below, unless a file overrides a key
  output_dir: chapters   # each file gets its own chapters/<stem>/ subfolder
  max_pages: 30          # still applies to manual chapters, same as the CLI default

files:
  - path: /path/to/book1.pdf
    chapters:                     # manual page ranges (1-indexed, inclusive) - skips detection
      - chapter 1, 1-10
      - chapter 2, 11-20

  - path: /path/to/book2.pdf
    chapters:
      - chapter 1, 1-14
      - chapter 2, 15-43

  - path: /path/to/book3.pdf       # no `chapters`: falls back to bookmark/heading detection
    bookmark_level: 1              # per-file override of defaults/CLI (wins over both)
    exclude_title: '^(Figures|Tables)$'
```

Any of `output_dir`, `mode`, `bookmark_level`, `exclude_title`, `min_gap`, `max_pages` can
be set in `defaults` (applies to every file) or on an individual file entry (wins over
`defaults` and the CLI flags for that file only). `output_dir` is always a parent directory -
every file's chapters land in `<output_dir>/<input-stem>/`, whether `output_dir` came from
`defaults`, a file's own entry, or `-o` on the command line. Two queue entries pointing at the
same source file (same stem) will still collide - give one of them its own distinct
`output_dir` in that case.

```bash
uv run knowledge-retrieval-split --queue queue.yaml --list   # preview every file's chapters first
uv run knowledge-retrieval-split --queue queue.yaml          # then actually write them
```

### Extract a page range

```bash
uv run knowledge-retrieval-extract input.pdf -p 3-7 -o out.pdf
uv run knowledge-retrieval-extract input.pdf -p 1,4,9 -o out.pdf
uv run knowledge-retrieval-extract input.pdf -p 1-3,7,10-12 -o out.pdf
```

Run `uv run knowledge-retrieval-extract -h` for the full option list.

### Scrape a single URL

```bash
uv run knowledge-retrieval-web https://example.com/article                     # crawl4ai + trafilatura (default)
uv run knowledge-retrieval-web https://example.com/article --engine firecrawl  # use the Firecrawl API instead
uv run knowledge-retrieval-web https://example.com/article -o article.md       # write to a specific file
```

With no `-o`, output goes to `outputs/<slug-of-the-url>.md` (e.g.
`outputs/example.com-article.md`), mirroring the PDF tools' `outputs/` convention.

Run `uv run knowledge-retrieval-web -h` for the full option list.

For scraping a whole list of URLs at once, with tiered fallback, PDF hand-off, and
recrawl dedup, see [Batch web crawling](#batch-web-crawling) below.

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

`tests/test_web.py`, `tests/test_crawl_router.py`, `tests/test_crawl_dedup.py`, and
`tests/test_crawl_cli.py` cover the web-scraping and batch-crawl tools without any
network access or browser - URL slugging, Trafilatura extraction quality on a fixed HTML
fixture, the tiering decision, dedup hashing, and the Tier 1 → Tier 2 fallback logic (with
Crawl4AI/Firecrawl mocked out). They run in the base `test` extra with no web extras
needed, though `tests/test_web.py`'s Trafilatura test skips itself if `trafilatura` isn't
installed.

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

## Web engines

| Engine      | Extra          | Package(s)                  | Notes |
|-------------|----------------|------------------------------|-------|
| `crawl4ai`  | `[crawl4ai]`   | `crawl4ai` + `trafilatura`  | default; headless-browser fetch (JS rendered) + Trafilatura content extraction, with Crawl4AI's own `fit_markdown` as a fallback if Trafilatura finds nothing extractable |
| `firecrawl` | `[firecrawl]`  | `firecrawl-py`               | hosted API; needs `FIRECRAWL_API_KEY` in `.env` (see Installation above) |

Select the engine with `--engine {crawl4ai,firecrawl}` on `knowledge-retrieval-web`.

## Batch web crawling

`knowledge-retrieval-crawl` scrapes a whole list of URLs in one run, routing each one
through a tiered pipeline instead of always using the same engine:

```bash
uv run knowledge-retrieval-crawl --input urls.txt --output out/
uv run knowledge-retrieval-crawl --input urls.csv --output out/ --force   # ignore dedup, reprocess everything
```

### Input list

`--input` accepts either format, chosen by file extension:

```
# urls.txt - one URL per line, optional ",known-hard" tag; blank lines and "#" comments ignored
https://example.com/article
https://example.com/spa-app,known-hard
```

```csv
# urls.csv - header row, optional known_hard column (1/true/yes)
url,known_hard
https://example.com/article,
https://example.com/spa-app,true
```

Tag a URL `known-hard` when you already know Crawl4AI won't handle it well - a
JavaScript-heavy SPA, an anti-bot-protected page, or anything login-gated - so the
pipeline skips straight to Firecrawl instead of wasting a Tier 1 attempt on it.

### How the tiering decision works

For each URL, in order:

1. **PDF branch** - if the URL's path ends in `.pdf`, it's downloaded and handed off to
   the existing PDF engines (`--engine` on `knowledge-retrieval`, default `mineru`) as a
   single document, no chapter splitting. This is a real conversion, not a stub, since
   the PDF engines already live in this repo.
2. **Tier 2 direct (`firecrawl`)** - if the URL is tagged `known-hard`, it goes straight
   to the Firecrawl API.
3. **Tier 1 (`crawl4ai`)** - otherwise, Crawl4AI fetches and renders the page, and
   Trafilatura extracts the main content from that same HTML. Both outputs are written
   side by side (`<name>.crawl4ai.md` and `<name>.trafilatura.md`) - the pipeline doesn't
   pick a winner between them yet, so you can compare quality across engines yourself.
4. **Tier 1 → Tier 2 fallback (`firecrawl-fallback`)** - if the Crawl4AI fetch raises an
   error, or both Crawl4AI's and Trafilatura's output come back under ~200 characters
   (a JS wall, an anti-bot block page, an empty app shell), the pipeline retries that URL
   through Firecrawl automatically.

A single URL failing (bad network, missing engine, etc.) is logged and skipped rather
than aborting the whole run; the process exits non-zero at the end if anything failed, so
it's safe to run from cron.

### Output

Each processed URL writes to `--output`:

- `<name>.md` (Tier 2 / PDF) or `<name>.crawl4ai.md` + `<name>.trafilatura.md` (Tier 1) -
  `<name>` is a filesystem-safe slug derived from the URL.
- `<name>.meta.json` - `source_url`, `fetched_at` (UTC), `tier`, `extractors`, and
  `content_hash`.
- `.dedup_index.json` - one shared index for the whole output directory, mapping each
  source URL to its last-seen content hash. Every URL is still fetched and its Markdown
  written on each run (the hash can only be known after fetching); what dedup skips is
  the `.meta.json` sidecar and the index update, for a URL whose extracted content hashes
  identically to last time. Pass `--force` to update the sidecar/index unconditionally too.

This output directory is a landing zone - promoting its contents into a vault or a RAG
index is a separate step, out of scope for this repo.

## Project layout

```
knowledge-retrieval/
├── src/knowledge_retrieval/
│   ├── pipeline.py          # unified PDF split+convert CLI
│   ├── split_chapters.py    # chapter splitting (bookmarks / heading heuristic)
│   ├── extract.py           # page-range extraction
│   ├── engines/             # mineru / marker / paddleocr wrappers
│   ├── web.py                # single-URL scrape CLI (knowledge-retrieval-web)
│   ├── web_engines/          # crawl4ai+trafilatura / firecrawl wrappers
│   ├── crawl_cli.py          # batch crawl CLI (knowledge-retrieval-crawl)
│   ├── crawl_router.py       # tiering decision + URL-list loading
│   ├── crawl_dedup.py        # content-hash dedup index
│   └── crawl_pdf.py          # PDF branch: download + hand off to engines/
├── references/               # source PDFs + split chapters (gitignored)
├── outputs/                  # converted Markdown / scraped pages (gitignored)
├── tests/                     # smoke + unit tests
├── .env.example               # FIRECRAWL_API_KEY template (copy to .env)
└── pyproject.toml
```

`references/`, `outputs/`, and `.env` are excluded from version control since they hold
local source documents, generated files, and credentials respectively.
