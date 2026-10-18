"""Write the embed outputs and manage the ChromaDB collection."""

from __future__ import annotations

import gc
import json
from pathlib import Path

import chromadb
import numpy as np
import pandas as pd
from chromadb.api.client import SharedSystemClient
from chromadb.errors import NotFoundError

from embed.texts import is_missing

COLLECTION_NAME = "book_descriptions"
ADD_BATCH = 1000


def write_arrays(
    out_dir: Path,
    embeddings: np.ndarray,
    work_ids: list[str],
    text_sources: list[str],
    texts: list[str],
) -> None:
    out_dir = Path(out_dir)
    np.save(out_dir / "desc_embeddings.npy", np.asarray(embeddings, dtype=np.float32))
    pd.DataFrame(
        {
            "row": range(len(work_ids)),
            "work_id": work_ids,
            "text_source": text_sources,
            "n_chars": [len(text) for text in texts],
        }
    ).to_parquet(out_dir / "desc_rows.parquet", index=False)


def write_meta(out_dir: Path, meta: dict) -> None:
    (Path(out_dir) / "meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")


def chroma_metadata(title, author, genre, year, text_source: str) -> dict:
    """Chroma rejects None values, so missing fields are left out and year is an int."""
    meta = {"title": str(title), "text_source": text_source}
    for key, value in (("author", author), ("genre", genre)):
        if not is_missing(value):
            meta[key] = str(value)
    if not is_missing(year):
        try:
            meta["year"] = int(year)
        except (TypeError, ValueError):
            pass
    return meta


def build_collection(chroma_dir: Path, ids, embeddings, documents, metadatas):
    client = chromadb.PersistentClient(path=str(chroma_dir))
    collection = client.create_collection(
        COLLECTION_NAME, configuration={"hnsw": {"space": "cosine"}}
    )
    embeddings = np.asarray(embeddings, dtype=np.float32)
    for start in range(0, len(ids), ADD_BATCH):
        end = start + ADD_BATCH
        collection.add(
            ids=list(ids[start:end]),
            embeddings=embeddings[start:end].tolist(),
            documents=list(documents[start:end]),
            metadatas=list(metadatas[start:end]),
        )
    return collection


def open_collection(chroma_dir: Path):
    if not Path(chroma_dir).is_dir():
        raise FileNotFoundError(
            f"No vector index at {chroma_dir}; run `python -m embed.run` first."
        )
    try:
        return chromadb.PersistentClient(path=str(chroma_dir)).get_collection(COLLECTION_NAME)
    except NotFoundError as exc:
        raise FileNotFoundError(
            f"{chroma_dir} has no `{COLLECTION_NAME}` collection (incomplete run?); "
            "re-run `python -m embed.run`."
        ) from exc


def search(collection, query_embedding, k: int = 5, genre: str | None = None) -> list[dict]:
    """Top-k books by cosine similarity; a genre filter also includes "both"."""
    k = min(k, collection.count())
    if k <= 0:
        return []
    kwargs = {
        "query_embeddings": [np.asarray(query_embedding, dtype=np.float32).tolist()],
        "n_results": k,
        "include": ["metadatas", "documents", "distances"],
    }
    if genre:
        kwargs["where"] = {"genre": {"$in": [genre, "both"]}}
    result = collection.query(**kwargs)
    hits = zip(
        result["ids"][0], result["metadatas"][0], result["documents"][0], result["distances"][0]
    )
    return [
        {
            "rank": rank,
            "work_id": work_id,
            "title": meta.get("title"),
            "author": meta.get("author"),
            "genre": meta.get("genre"),
            "text_source": meta.get("text_source"),
            "similarity": round(1.0 - float(distance), 4),
            "document": document,
        }
        for rank, (work_id, meta, document, distance) in enumerate(hits, start=1)
    ]


def release_chroma() -> None:
    """Close Chroma's cached clients so Windows lets us rename/delete the folder."""
    SharedSystemClient.clear_system_cache()
    gc.collect()
