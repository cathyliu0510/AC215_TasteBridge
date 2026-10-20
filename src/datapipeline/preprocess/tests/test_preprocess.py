"""Tests for preprocess.py. All data is invented (synthetic_raw.py or tiny hand-made files)."""

import gzip
import json

import pandas as pd
import pytest

import preprocess
from preprocess import LIKE_THRESHOLD, Settings, run, select_catalogue, summarize_work
from quality import is_generic_shelf
from synthetic_raw import make_raw


def _settings(tmp_path, **overrides):
    values = dict(
        raw_dir=tmp_path / "raw",
        out_dir=tmp_path / "processed",
        max_works=5000,
        max_interactions=500_000,
        min_user_likes=5,
        seed=42,
        log_every=10**9,
    )
    values.update(overrides)
    return Settings(**values)


@pytest.fixture(scope="module")
def synthetic_run(tmp_path_factory):
    """One full run on invented Goodreads-shaped data, shared by the contract tests."""
    tmp = tmp_path_factory.mktemp("run")
    make_raw(tmp / "raw", n_works=300, n_users=800, seed=3)
    manifest = run(_settings(tmp, max_works=200))
    books = pd.read_parquet(tmp / "processed" / "books.parquet")
    inter = pd.read_parquet(tmp / "processed" / "interactions.parquet")
    return tmp, manifest, books, inter


# ------------------------------------------------------------ output contract
def test_books_contract_for_embed_and_backend(synthetic_run):
    _, _, books, _ = synthetic_run
    # Columns embed requires (embed/inputs.py REQUIRED_COLUMNS) plus the ones it uses.
    for col in ("work_id", "title", "author", "description", "shelves", "has_description", "genre", "year"):
        assert col in books.columns
    assert books["work_id"].is_unique
    assert books["title"].str.len().gt(0).all()
    assert books["has_description"].dtype == bool


def test_books_contract_for_evaluation(synthetic_run):
    _, _, books, _ = synthetic_run
    # evaluation/data.py BOOK_COLUMNS = ("work_id", "genres"); genres is a list.
    assert set(books["genre"]) <= {"fantasy", "mystery", "both"}
    for genre, genres in zip(books["genre"], books["genres"]):
        assert (genre == "both") == (len(genres) == 2)
        assert set(genres) <= {"fantasy", "mystery"}


def test_shelves_are_cleaned(synthetic_run):
    _, _, books, _ = synthetic_run
    all_shelves = {s for shelves in books["shelves"] for s in shelves}
    assert all_shelves  # something survives
    assert not any(is_generic_shelf(s) for s in all_shelves)  # no to-read, favorites, ...


def test_interactions_contract(synthetic_run):
    _, _, books, inter = synthetic_run
    assert list(inter.columns) == ["user_id", "work_id", "rating", "is_read"]
    assert not inter.duplicated(["user_id", "work_id"]).any()  # editions merged
    assert inter["rating"].between(0, 5).all()
    assert set(inter["work_id"]) <= set(books["work_id"])
    # no bare "to-read" rows: every row is read or rated
    assert (inter["is_read"] | inter["rating"].gt(0)).all()


def test_every_user_has_enough_likes(synthetic_run):
    _, _, _, inter = synthetic_run
    likes = inter[inter["rating"] >= LIKE_THRESHOLD].groupby("user_id").size()
    assert likes.min() >= 5
    assert inter["user_id"].nunique() == len(likes)


def test_catalogue_cap(synthetic_run):
    _, manifest, books, _ = synthetic_run
    assert len(books) <= 200
    assert manifest["counts"]["catalogue_works"] == len(books)


def test_manifest_records_versions(synthetic_run):
    tmp, manifest, _, _ = synthetic_run
    on_disk = json.loads((tmp / "processed" / "manifest.json").read_text())
    assert on_disk["data_version"].startswith("gr-")
    assert on_disk["inputs"]["mode"] == "synthetic"  # copied from the ingest manifest
    assert set(on_disk["files"]) == {"books.parquet", "interactions.parquet"}
    assert on_disk["quality"]["shelf_blocklist_version"]
    assert on_disk["code_version"]


def test_same_input_gives_same_data_version(tmp_path, synthetic_run):
    src, first, _, _ = synthetic_run
    second = run(_settings(tmp_path, raw_dir=src / "raw", max_works=200))
    assert second["data_version"] == first["data_version"]


def test_interaction_cap_samples_whole_users(tmp_path):
    make_raw(tmp_path / "raw", n_works=150, n_users=400, seed=5)
    manifest = run(_settings(tmp_path, max_interactions=3000))
    inter = pd.read_parquet(tmp_path / "processed" / "interactions.parquet")
    assert len(inter) <= 3000
    assert manifest["counts"]["interactions"] == len(inter)


def test_rerun_replaces_folder_cleanly(tmp_path):
    make_raw(tmp_path / "raw", n_works=80, n_users=200, seed=9)
    run(_settings(tmp_path))
    run(_settings(tmp_path, max_works=50))
    names = sorted(p.name for p in tmp_path.iterdir())
    assert names == ["processed", "raw"]  # no .tmp / .old left over


# ------------------------------------------------------- edition-level logic
def _write(path, records):
    with gzip.open(path, "wt", encoding="utf-8") as handle:
        for rec in records:
            handle.write(json.dumps(rec) + "\n")


def test_two_editions_become_one_row_with_best_rating(tmp_path):
    raw = tmp_path / "raw"
    raw.mkdir()
    shelves = [{"count": "10", "name": "fantasy"}]
    ed = lambda b, w, rc: {"book_id": b, "work_id": w, "title": f"T{w}", "ratings_count": rc,
                           "authors": [{"author_id": "1", "role": ""}], "popular_shelves": shelves,
                           "description": "A long enough invented description for the quality check."}
    _write(raw / "books_fantasy.json.gz", [ed("1", "W1", "100"), ed("2", "W1", "5"), ed("3", "W2", "1")])
    _write(raw / "books_mystery.json.gz", [])
    # user u1 rates both editions of W1 (3 and 5): one row with rating 5 must remain.
    rows = [{"user_id": "u1", "book_id": "1", "rating": 3, "is_read": True},
            {"user_id": "u1", "book_id": "2", "rating": 5, "is_read": True},
            {"user_id": "u1", "book_id": "3", "rating": 4, "is_read": True}]
    _write(raw / "inter_fantasy.json.gz", rows)
    _write(raw / "inter_mystery.json.gz", [])
    _write(raw / "authors.json.gz", [{"author_id": "1", "name": "Invented Author"}])

    run(_settings(tmp_path, min_user_likes=1))
    inter = pd.read_parquet(tmp_path / "processed" / "interactions.parquet")
    books = pd.read_parquet(tmp_path / "processed" / "books.parquet")
    w1 = inter[inter["work_id"] == "W1"]
    assert len(w1) == 1 and w1["rating"].iloc[0] == 5
    assert books.set_index("work_id").loc["W1", "n_editions"] == 2
    assert books.set_index("work_id").loc["W1", "author"] == "Invented Author"


def test_summarize_work_picks_most_rated_edition():
    editions = [
        {"book_id": "2", "title": "Rare", "author_id": "9", "year": 2001, "ratings_count": 3,
         "description": "", "popular_shelves": []},
        {"book_id": "1", "title": "Main", "author_id": "7", "year": 1999, "ratings_count": 90,
         "description": "", "popular_shelves": []},
    ]
    row = summarize_work("W", editions)
    assert row["title"] == "Main" and row["author_id"] == "7" and row["year"] == 1999
    assert row["n_ratings"] == 93


def test_select_catalogue_is_deterministic():
    from collections import Counter
    likes = Counter({"b": 5, "a": 5, "c": 9})
    assert select_catalogue(likes, 2) == ["c", "a"]  # ties broken by work_id


def test_missing_raw_files_fail_with_clear_message(tmp_path, monkeypatch):
    monkeypatch.setenv("RAW_DIR", str(tmp_path / "nothing"))
    monkeypatch.setenv("PROCESSED_DIR", str(tmp_path / "processed"))
    assert preprocess.main() == 1


def test_bad_setting_is_rejected(monkeypatch):
    monkeypatch.setenv("PREPROCESS_MAX_WORKS", "0")
    with pytest.raises(ValueError):
        Settings.from_env()
