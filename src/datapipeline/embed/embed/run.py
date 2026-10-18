"""Embed stage entry point: python -m embed.run

Reads books.parquet, writes data/embeddings/ atomically: everything goes to
<output>.tmp first and is renamed into place only when complete, so a failed
run never replaces good output.
"""

from __future__ import annotations

import logging
import os
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

from embed.config import ConfigError, Settings
from embed.encoder import EmbeddingError, SentenceTransformerEncoder, check_embeddings
from embed.inputs import InputError, load_books, read_upstream_version, sha256_file
from embed.query import run_examples, write_examples
from embed.store import build_collection, chroma_metadata, release_chroma, write_arrays, write_meta
from embed.texts import MIN_DESCRIPTION_CHARS, build_texts

log = logging.getLogger("embed")
_FORMAT = "%(asctime)s %(levelname)s %(message)s"


def _column(books, name: str) -> list:
    return list(books[name]) if name in books.columns else [None] * len(books)


def _swap_into_place(tmp: Path, out: Path) -> None:
    old = out.with_name(out.name + ".old")
    if old.exists():  # out exists too (run() restores a lone .old), so this copy is stale
        shutil.rmtree(old)
    if out.exists():
        out.rename(old)
    try:
        tmp.rename(out)
    except BaseException:
        if old.exists() and not out.exists():
            old.rename(out)  # put the previous output back
        raise
    if old.exists():
        shutil.rmtree(old)


def run(settings: Settings, encoder=None) -> dict:
    out = Path(settings.output_dir)
    tmp = out.with_name(out.name + ".tmp")
    old = out.with_name(out.name + ".old")
    if old.exists() and not out.exists():
        log.warning("restoring %s left behind by an interrupted run", old)
        old.rename(out)
    books = load_books(settings.input_path)  # a missing input is reported before any write
    if tmp.exists():
        shutil.rmtree(tmp)
    try:
        tmp.mkdir(parents=True)
    except PermissionError as exc:
        uid = os.getuid() if hasattr(os, "getuid") else 1000  # the container runs as uid 1000
        raise OSError(
            f"cannot write to {tmp.parent} ({exc}). On Linux, a ./data folder first created "
            f"by Docker belongs to root: run `sudo chown -R {uid} data` on the host and re-run"
        ) from exc

    handler = logging.FileHandler(tmp / "run.log", encoding="utf-8")
    handler.setFormatter(logging.Formatter(_FORMAT))
    log.addHandler(handler)
    log.setLevel(logging.INFO)

    def close_log() -> None:
        log.removeHandler(handler)
        handler.close()

    try:
        log.info("embed: read %s", settings.input_path)
        if "has_description" not in books.columns:
            log.warning(
                "has_description column absent; applying the local %d-char rule",
                MIN_DESCRIPTION_CHARS,
            )
        texts, sources = build_texts(books)
        n_fallback = sum(source == "title_shelves" for source in sources)
        log.info("books=%d fallback_text=%d", len(books), n_fallback)

        if encoder is None:
            log.info("loading %s @ %s", settings.model_name, settings.model_revision)
            encoder = SentenceTransformerEncoder(
                settings.model_name, settings.model_revision, settings.batch_size
            )
        embeddings = encoder.encode(texts)
        check_embeddings(embeddings, len(texts))

        ids = books["work_id"].tolist()
        write_arrays(tmp, embeddings, ids, sources, texts)
        metadatas = [
            chroma_metadata(title, author, genre, year, source)
            for title, author, genre, year, source in zip(
                books["title"], books["author"], _column(books, "genre"),
                _column(books, "year"), sources,
            )
        ]
        collection = build_collection(tmp / "chroma", ids, embeddings, texts, metadatas)
        examples = run_examples(
            collection, encoder, settings.example_queries, excerpts=settings.evidence_excerpts
        )
        write_examples(tmp, examples)
        del collection

        meta = {
            "stage": "embed",
            "embedding_model": encoder.model_name,
            "model_revision": encoder.revision,
            "dim": int(embeddings.shape[1]),
            "num_books": len(ids),
            "num_fallback_text": int(n_fallback),
            "input_file": str(settings.input_path),
            "input_sha256": sha256_file(settings.input_path),
            "input_data_version": read_upstream_version(settings.input_path),
            "code_version": settings.code_version,
            "created_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
        write_meta(tmp, meta)
        log.info("embed: wrote %d x %d embeddings and the vector index", *embeddings.shape)
    except BaseException:
        close_log()
        release_chroma()
        shutil.rmtree(tmp, ignore_errors=True)
        raise

    close_log()
    release_chroma()  # Windows: Chroma must let go of its files before the rename
    try:
        _swap_into_place(tmp, out)
    except OSError as exc:
        shutil.rmtree(tmp, ignore_errors=True)
        raise OSError(
            f"could not replace {out} ({exc}); the previous output was kept. "
            "close any program using it (for example `python -m embed.query` or a notebook) "
            "and re-run"
        ) from exc
    log.info("embed: output ready at %s", out)
    return meta


def main() -> int:
    logging.basicConfig(stream=sys.stdout, level=logging.INFO, format=_FORMAT)
    try:
        run(Settings.from_env())
    except (ConfigError, InputError, EmbeddingError, OSError) as exc:
        log.error("embed failed: %s", exc)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
