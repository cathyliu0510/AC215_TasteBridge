import json

import numpy as np
import pandas as pd
import pytest

from embed.store import (
    build_collection,
    chroma_metadata,
    open_collection,
    release_chroma,
    search,
    write_arrays,
    write_meta,
)
from embed.texts import build_texts


def _index(tmp_path, encoder, books_df, folder="index"):
    texts, sources = build_texts(books_df)
    emb = encoder.encode(texts)
    ids = books_df["work_id"].tolist()
    metas = [
        chroma_metadata(t, a, g, y, s)
        for t, a, g, y, s in zip(
            books_df["title"], books_df["author"], books_df["genre"], books_df["year"], sources
        )
    ]
    collection = build_collection(tmp_path / folder / "chroma", ids, emb, texts, metas)
    return collection, emb, ids


def test_write_arrays_and_meta(tmp_path, encoder):
    emb = encoder.encode(["a", "bb"])
    write_arrays(tmp_path, emb, ["w1", "w2"], ["description", "title_shelves"], ["a", "bb"])
    assert np.array_equal(np.load(tmp_path / "desc_embeddings.npy"), emb)
    rows = pd.read_parquet(tmp_path / "desc_rows.parquet")
    assert rows.columns.tolist() == ["row", "work_id", "text_source", "n_chars"]
    assert rows["work_id"].tolist() == ["w1", "w2"]
    assert rows["n_chars"].tolist() == [1, 2]
    write_meta(tmp_path, {"stage": "embed"})
    assert json.loads((tmp_path / "meta.json").read_text(encoding="utf-8")) == {"stage": "embed"}


def test_chroma_metadata_drops_missing_and_casts_year():
    assert chroma_metadata("T", None, None, pd.NA, "description") == {
        "title": "T", "text_source": "description"
    }
    meta = chroma_metadata("T", "A", "fantasy", 2001.0, "title_shelves")
    assert meta == {"title": "T", "text_source": "title_shelves", "author": "A",
                    "genre": "fantasy", "year": 2001}
    assert isinstance(meta["year"], int)
    assert chroma_metadata("T", "A", "both", np.int64(1999), "description")["year"] == 1999
    assert "year" not in chroma_metadata("T", "A", "both", float("nan"), "description")


def test_build_and_search_round_trip(tmp_path, encoder, books_df):
    collection, emb, ids = _index(tmp_path, encoder, books_df)
    results = search(collection, emb[2], k=3)
    assert [r["rank"] for r in results] == [1, 2, 3]
    assert results[0]["work_id"] == ids[2]
    assert results[0]["similarity"] == pytest.approx(1.0, abs=1e-3)
    assert results[0]["title"] == "The Lantern School"
    assert results[0]["document"].startswith("The Lantern School by Ines Harrow.")
    release_chroma()


def test_search_genre_filter_includes_both(tmp_path, encoder, books_df):
    collection, emb, _ = _index(tmp_path, encoder, books_df)
    results = search(collection, emb[0], k=8, genre="mystery")
    genres = {r["genre"] for r in results}
    assert genres <= {"mystery", "both"}
    assert "syn-004" in {r["work_id"] for r in results}  # the "both" book
    release_chroma()


def test_search_k_larger_than_collection(tmp_path, encoder, books_df):
    collection, emb, _ = _index(tmp_path, encoder, books_df)
    assert len(search(collection, emb[0], k=50)) == 8
    release_chroma()


def test_open_collection_missing_dir(tmp_path):
    with pytest.raises(FileNotFoundError, match="embed.run"):
        open_collection(tmp_path / "nothing" / "chroma")


def test_release_allows_rename(tmp_path, encoder, books_df):
    _index(tmp_path, encoder, books_df, folder="a")
    release_chroma()
    (tmp_path / "a").rename(tmp_path / "b")
    assert open_collection(tmp_path / "b" / "chroma").count() == 8
    release_chroma()
