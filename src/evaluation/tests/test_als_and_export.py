"""Tests for B2 ALS (als.py) and the artifact export (export.py). Invented data only."""

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from evaluation import synthetic
from evaluation.als import ALS, ALSParams
from evaluation.export import check_artifacts, export, main as export_main

FAST = ALSParams(factors=8, regularization=1.0, alpha=10.0, iterations=5, seed=0)


def _two_cluster_interactions() -> pd.DataFrame:
    """Readers 0-19 like works a0-a4, readers 20-39 like b0-b4: two clean taste groups."""
    rows = []
    for u in range(40):
        group = "a" if u < 20 else "b"
        for i in range(5):
            rows.append({"user_id": f"u{u}", "work_id": f"{group}{i}", "rating": 5})
    return pd.DataFrame(rows)


def test_als_learns_taste_groups() -> None:
    model = ALS(FAST).fit(_two_cluster_interactions())
    scores = dict(zip(model.items, model.score(["a0", "a1"])))
    # Works from the same group score higher than the other group's works.
    assert min(scores[w] for w in ("a2", "a3", "a4")) > max(scores[w] for w in ("b0", "b1", "b2"))


def test_als_vectors_are_unit_length_and_scores_are_cosines() -> None:
    model = ALS(FAST).fit(_two_cluster_interactions())
    assert np.allclose(np.linalg.norm(model.item_vectors, axis=1), 1.0, atol=1e-5)
    scores = model.score(["a0"])
    assert scores.min() >= -1.0001 and scores.max() <= 1.0001


def test_als_matches_backend_rule() -> None:
    """taste = unit mean of seed vectors; fit = dot with unit item vectors (backend recommender.py)."""
    model = ALS(FAST).fit(_two_cluster_interactions())
    rows = [model.items.index(w) for w in ("a0", "b1")]
    mean = model.item_vectors[rows].mean(axis=0)
    expected = model.item_vectors @ (mean / np.linalg.norm(mean))
    assert np.allclose(model.score(["a0", "b1"]), expected, atol=1e-5)


def test_als_is_deterministic_and_ignores_unknown_favorites() -> None:
    data = _two_cluster_interactions()
    first, second = ALS(FAST).fit(data), ALS(FAST).fit(data)
    assert np.array_equal(first.item_vectors, second.item_vectors)
    assert not first.score(["not-a-work"]).any()


def test_als_rejects_bad_params() -> None:
    with pytest.raises(ValueError):
        ALS(ALSParams(factors=0))


@pytest.fixture
def processed(tmp_path: Path) -> Path:
    """A data/processed/ folder in the preprocess output format, from synthetic data."""
    inter, books = synthetic.generate(seed=1)
    folder = tmp_path / "processed"
    folder.mkdir()
    inter["is_read"] = True
    inter.to_parquet(folder / "interactions.parquet", index=False)
    books = books.assign(
        title="Book " + books["work_id"].astype(str),
        author="Invented Author",
        year=pd.array([2001] * len(books), dtype="Int64"),
        shelves=[["fantasy", "heist"]] * len(books),
    )
    books.to_parquet(folder / "books.parquet", index=False)
    (folder / "manifest.json").write_text(json.dumps({"data_version": "gr-test123"}))
    return folder


def test_export_writes_a_folder_the_backend_accepts(processed: Path, tmp_path: Path) -> None:
    target = export(processed, tmp_path / "artifacts", FAST)
    current = tmp_path / "artifacts" / "current"
    for folder in (target, current):
        books = json.loads((folder / "books.json").read_text())
        emb = np.load(folder / "item_embeddings.npy")
        coords = np.load(folder / "coords_2d.npy")
        meta = json.loads((folder / "meta.json").read_text())
        assert len(books) == emb.shape[0] == coords.shape[0] > 0
        assert emb.dtype == np.float32 and coords.shape[1] == 2
        assert np.abs(coords).max() <= 1.0 + 1e-6
        assert meta["model_version"] == "b2-als-gr-test123"
        assert meta["data_version"] == "gr-test123"
        assert set(books[0]) == {"book_id", "title", "author", "year", "shelves", "cover_url"}


def test_export_keeps_catalogue_order(processed: Path, tmp_path: Path) -> None:
    export(processed, tmp_path / "artifacts", FAST)
    exported = [b["book_id"] for b in json.loads((tmp_path / "artifacts/current/books.json").read_text())]
    original = pd.read_parquet(processed / "books.parquet")["work_id"].astype(str).tolist()
    assert exported == [w for w in original if w in set(exported)]


def test_check_artifacts_catches_mismatched_rows() -> None:
    books = [{"book_id": "1"}, {"book_id": "2"}]
    with pytest.raises(ValueError, match="row counts"):
        check_artifacts(books, np.ones((3, 4), np.float32), np.zeros((2, 2), np.float32))
    with pytest.raises(ValueError, match="duplicate"):
        check_artifacts([{"book_id": "1"}] * 2, np.ones((2, 4), np.float32), np.zeros((2, 2), np.float32))


def test_export_cli_reports_missing_input(tmp_path: Path) -> None:
    assert export_main(["--processed", str(tmp_path / "nope"), "--out", str(tmp_path / "out")]) == 1
