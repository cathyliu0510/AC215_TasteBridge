import pandas as pd
import pytest

from embed.inputs import InputError, load_books, read_upstream_version, sha256_file


def _write(tmp_path, books):
    path = tmp_path / "books.parquet"
    books.to_parquet(path, index=False)
    return path


def test_load_books_ok(books_path):
    books = load_books(books_path)
    assert len(books) == 8
    assert books["work_id"].tolist()[0] == "syn-001"


def test_numeric_work_ids_become_strings(tmp_path, books_df):
    books_df["work_id"] = range(100, 108)
    books = load_books(_write(tmp_path, books_df))
    assert books["work_id"].tolist()[:2] == ["100", "101"]


def test_missing_file_names_producer(tmp_path):
    with pytest.raises(InputError, match="preprocess"):
        load_books(tmp_path / "nope.parquet")


def test_not_parquet(tmp_path):
    path = tmp_path / "books.parquet"
    path.write_text("hello", encoding="utf-8")
    with pytest.raises(InputError, match="parquet"):
        load_books(path)


def test_missing_columns_listed(tmp_path, books_df):
    path = _write(tmp_path, books_df.drop(columns=["author", "shelves"]))
    with pytest.raises(InputError, match="author, shelves"):
        load_books(path)


def test_zero_rows(tmp_path, books_df):
    with pytest.raises(InputError, match="zero rows"):
        load_books(_write(tmp_path, books_df.iloc[0:0]))


def test_null_work_id(tmp_path, books_df):
    books_df["work_id"] = books_df["work_id"].astype(object)
    books_df.loc[2, "work_id"] = None
    with pytest.raises(InputError, match="null work_id"):
        load_books(_write(tmp_path, books_df))


def test_duplicate_work_ids(tmp_path, books_df):
    path = _write(tmp_path, pd.concat([books_df, books_df.iloc[[0]]]))
    with pytest.raises(InputError, match="syn-001"):
        load_books(path)


def test_duplicates_listing_is_capped(tmp_path):
    ids = [f"w{i}" for i in range(12)] * 2
    books = pd.DataFrame(
        {"work_id": ids, "title": "T", "author": "A", "description": None, "shelves": [[]] * 24}
    )
    with pytest.raises(InputError, match=r"\(\+2 more\)"):
        load_books(_write(tmp_path, books))


def test_empty_title(tmp_path, books_df):
    books_df.loc[1, "title"] = "   "
    with pytest.raises(InputError, match="syn-002"):
        load_books(_write(tmp_path, books_df))


def test_sha256_and_upstream_version(books_path, tmp_path):
    assert len(sha256_file(books_path)) == 64
    assert read_upstream_version(books_path) == "synthetic-test"
    (books_path.parent / "manifest.json").write_text("{not json", encoding="utf-8")
    assert read_upstream_version(books_path) is None
    assert read_upstream_version(tmp_path / "elsewhere" / "books.parquet") is None


def test_raw_goodreads_shelves_are_rejected(tmp_path, books_df):
    books_df["shelves"] = [[{"name": "heist", "count": "10"}, {"name": "to-read", "count": "99"}]] * 8
    with pytest.raises(InputError, match="add_quality_flags"):
        load_books(_write(tmp_path, books_df))
