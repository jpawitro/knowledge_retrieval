"""Wraps the PaddleOCR PP-StructureV3 pipeline for batch PDF -> Markdown conversion.

Runs in-process rather than shelling out to the vendor's own `paddleocr
pp_structurev3` CLI: PP-StructureV3.predict() yields one result per *page*, and
that CLI saves each page result independently, so on a multi-page chapter PDF
every page after the first would silently overwrite the same `<stem>.md`. The
documented fix is to merge page results with concatenate_markdown_pages()
before writing, which only the Python API lets us do.
"""
# pylint: disable=duplicate-code
# mineru.py and paddleocr.py share the same "resolve pdf_files, workers<=1 vs
# sharded" shape by design, so they read the same at a glance - that's
# deliberate consistency across sibling modules, not copy-paste debt.

import importlib.util
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

PACKAGE = "paddleocr[doc-parser]"


def _convert_one(pdf_path: Path, output_dir: Path, pipeline) -> None:
    """Run one PDF through PPStructureV3 and write its merged markdown."""
    results = list(pipeline.predict(str(pdf_path)))
    markdown_list = [res.markdown for res in results]
    merged = pipeline.concatenate_markdown_pages(markdown_list)

    doc_dir = output_dir / pdf_path.stem
    doc_dir.mkdir(parents=True, exist_ok=True)
    merged.save_to_markdown(doc_dir / f"{pdf_path.stem}.md")


def _convert_shard(pdf_paths: list[Path], output_dir: Path) -> None:
    """Convert a shard of files sequentially with one shared PPStructureV3 instance."""
    # Deferred: keeps `import knowledge_retrieval.engines` working when paddleocr
    # isn't installed, so other engines stay usable without this optional extra.
    from paddleocr import PPStructureV3  # pylint: disable=import-outside-toplevel

    pipeline = PPStructureV3()
    for pdf_path in pdf_paths:
        _convert_one(pdf_path, output_dir, pipeline)


def convert(input_dir: Path, output_dir: Path, workers: int, extra_args: list[str]) -> None:
    """Convert every PDF in `input_dir` to Markdown via PP-StructureV3."""
    if importlib.util.find_spec("paddleocr") is None:
        raise RuntimeError(
            f"'paddleocr' is not installed. Install it with 'pip install {PACKAGE}'."
        )

    if extra_args:
        raise RuntimeError(
            "The paddleocr engine runs PP-StructureV3 in-process (not as a CLI "
            f"subprocess), so extra engine args aren't supported: {extra_args}"
        )

    output_dir.mkdir(parents=True, exist_ok=True)
    pdf_files = sorted(input_dir.glob("*.pdf"))
    if not pdf_files:
        return

    if workers <= 1:
        # One PPStructureV3 pipeline loads its model stack once and processes
        # every file in input_dir sequentially - the cheapest option, and the
        # default.
        _convert_shard(pdf_files, output_dir)
        return

    # Opt-in only: each shard is its own process with its own PPStructureV3
    # instance and full model stack loaded, same tradeoff as marker's --workers.
    shards = [pdf_files[i::workers] for i in range(workers)]
    shards = [shard for shard in shards if shard]
    with ProcessPoolExecutor(max_workers=len(shards)) as executor:
        futures = [executor.submit(_convert_shard, shard, output_dir) for shard in shards]
        for future in futures:
            future.result()
