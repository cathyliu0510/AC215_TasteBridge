"""Tests for quality.py. All data here is invented, never real Goodreads data."""

import json

import numpy as np
import pandas as pd
import pytest

from quality import (
    MIN_DESCRIPTION_CHARS,
    SHELF_BLOCKLIST,
    SHELF_RULES_VERSION,
    add_quality_flags,
    check_description,
    clean_description,
    clean_shelves,
    is_generic_shelf,
    normalize_shelf,
)


# ---------------------------------------------------------------- descriptions


@pytest.mark.parametrize(
    "raw", [None, float("nan"), pd.NA, np.nan, "", "   ", "<br><br>", "<p> </p>"]
)
def test_clean_description_missing(raw):
    assert clean_description(raw) is None


def test_clean_description_strips_tags_then_unescapes():
    raw = "<b>Locke Lamora</b> is a thief.<br>A very good one, in a city of canals."
    assert clean_description(raw) == (
        "Locke Lamora is a thief. A very good one, in a city of canals."
    )


def test_clean_description_keeps_escaped_angle_brackets():
    assert clean_description("Book 2 of &lt;Gentleman Bastard&gt;") == (
        "Book 2 of <Gentleman Bastard>"
    )


def test_clean_description_decodes_entities_and_collapses_whitespace():
    assert clean_description("Cats &amp; dogs\n\n\tforever") == "Cats & dogs forever"


def test_check_description_missing():
    assert check_description(None) == (None, "missing")
    assert check_description("<br>") == (None, "missing")


def test_check_description_too_short_keeps_text():
    assert check_description("A novel.") == ("A novel.", "too_short")


def test_check_description_boundary_is_inclusive():
    exactly = "x" * MIN_DESCRIPTION_CHARS
    assert check_description(exactly) == (exactly, None)
    assert check_description(exactly[:-1]) == (exactly[:-1], "too_short")


def test_check_description_custom_threshold():
    assert check_description("A novel.", min_chars=5) == ("A novel.", None)


# --------------------------------------------------------------------- shelves


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("Found Family", "found-family"),
        ("sci_fi", "science-fiction"),
        ("Sci-Fi", "science-fiction"),
        ("scifi", "science-fiction"),
        ("YA", "young-adult"),
        ("  to--read ", "to-read"),
        ("Favourites", "favorites"),
        ("-heist-", "heist"),
    ],
)
def test_normalize_shelf(raw, expected):
    assert normalize_shelf(raw) == expected


@pytest.mark.parametrize("name", sorted(SHELF_BLOCKLIST))
def test_blocklist_entries_are_generic(name):
    assert is_generic_shelf(name)


@pytest.mark.parametrize(
    "name",
    [
        "2015", "read-in-2016", "2017-reads", "2017-read", "read-2018",
        "5-stars", "4stars", "1-star", "3.stars",
        "to-read-fantasy", "owned-hardcover", "kindle-unlimited", "tbr-2019",
        "To-Read", "Currently Reading",
    ],
)
def test_pattern_and_case_variants_are_generic(name):
    assert is_generic_shelf(name)


@pytest.mark.parametrize(
    "name",
    [
        "heist", "fantasy", "mystery", "1920s", "historical-fiction",
        "wish-fulfillment", "found-family", "science-fiction", "young-adult",
        "magic-school",
    ],
)
def test_content_shelves_are_kept(name):
    assert not is_generic_shelf(name)


def test_clean_shelves_spec_example():
    raw = [
        {"name": "to-read", "count": "5120"},
        {"name": "fantasy", "count": "2100"},
        {"name": "currently-reading", "count": "900"},
        {"name": "favorites", "count": "450"},
        {"name": "heist", "count": "310"},
        {"name": "kindle", "count": "120"},
        {"name": "Found Family", "count": "95"},
        {"name": "2017-reads", "count": "40"},
    ]
    assert clean_shelves(raw) == ["fantasy", "heist", "found-family"]


def test_clean_shelves_merges_after_normalization():
    raw = [
        {"name": "sci-fi", "count": "2"},
        {"name": "heist", "count": "3"},
        {"name": "Science Fiction", "count": "2"},
    ]
    assert clean_shelves(raw) == ["science-fiction", "heist"]


def test_clean_shelves_min_count_and_top_n():
    raw = [{"name": f"tag-{i}", "count": str(100 - i)} for i in range(30)]
    raw.append({"name": "rare", "count": "2"})
    assert clean_shelves(raw, min_count=3, top_n=20) == [f"tag-{i}" for i in range(20)]
    assert "rare" not in clean_shelves(raw, min_count=3, top_n=50)


def test_clean_shelves_ties_keep_first_seen_order():
    raw = [
        {"name": "beta", "count": "5"},
        {"name": "alpha", "count": "5"},
        {"name": "gamma", "count": "9"},
    ]
    assert clean_shelves(raw) == ["gamma", "beta", "alpha"]


def test_clean_shelves_plain_strings_count_as_infinite():
    assert clean_shelves(["heist", "to-read", "Found Family"]) == ["heist", "found-family"]


def test_clean_shelves_count_with_thousands_separator():
    raw = [{"name": "heist", "count": "1,234"}, {"name": "caper", "count": "2,000"}]
    assert clean_shelves(raw) == ["caper", "heist"]


@pytest.mark.parametrize("raw", [None, float("nan"), pd.NA, [], np.array([], dtype=object)])
def test_clean_shelves_empty_inputs(raw):
    assert clean_shelves(raw) == []


def test_clean_shelves_accepts_numpy_array_from_parquet():
    raw = np.array(
        [{"name": "heist", "count": "10"}, {"name": "to-read", "count": "99"}], dtype=object
    )
    assert clean_shelves(raw) == ["heist"]


def test_clean_shelves_skips_unknown_shapes():
    raw = [
        {"name": "heist", "count": "10"},
        {"count": "5"},
        {"name": None, "count": "5"},
        42,
        None,
        {"name": "caper", "count": "lots"},
    ]
    assert clean_shelves(raw) == ["heist"]


# ------------------------------------------------------------ add_quality_flags


def _books() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "work_id": ["w1", "w2", "w3", "w4"],
            "title": ["Glass Heist", "Book Two", "Quiet Orchard", "Lantern School"],
            "description": [
                "<b>A crew</b> of con artists plans an impossible robbery.",
                "Book 2.",
                None,
                "  ",
            ],
            "shelves": [
                [{"name": "heist", "count": "10"}, {"name": "to-read", "count": "99"}],
                ["fantasy"],
                [],
                None,
            ],
            "year": [2001, 2002, None, 2004],
        }
    )


def test_adds_columns_with_expected_values():
    out, _ = add_quality_flags(_books())
    assert out["has_description"].tolist() == [True, False, False, False]
    assert out["description_issue"].fillna("ok").tolist() == [
        "ok", "too_short", "missing", "missing"
    ]
    assert out["description"].iloc[0] == "A crew of con artists plans an impossible robbery."
    assert out["description"].iloc[1] == "Book 2."
    assert out["description"].iloc[2:].isna().all()
    assert out["shelves"].tolist() == [["heist"], ["fantasy"], [], []]
    assert out["has_description"].dtype == bool
    assert str(out["description_issue"].dtype) == "string"


def test_invariants_hold():
    out, _ = add_quality_flags(_books())
    assert (out["has_description"] == out["description_issue"].isna()).all()
    missing = out["description_issue"].eq("missing").fillna(False).astype(bool)
    assert out.loc[missing, "description"].isna().all()


def test_does_not_mutate_input_and_preserves_order():
    books = _books()
    before = books.copy(deep=True)
    out, _ = add_quality_flags(books)
    pd.testing.assert_frame_equal(books, before)
    assert out["work_id"].tolist() == ["w1", "w2", "w3", "w4"]
    assert out.index.equals(books.index)
    pd.testing.assert_series_equal(out["year"], books["year"])


def test_summary_counts_and_json_safe():
    _, summary = add_quality_flags(_books())
    assert summary == {
        "n_books": 4,
        "n_missing_description": 2,
        "n_too_short_description": 1,
        "n_books_no_shelves_after_clean": 2,
        "shelves_raw_total": 3,
        "shelves_kept_total": 2,
        "n_unknown_shelf_entries": 0,
        "min_description_chars": 40,
        "min_shelf_count": 3,
        "top_n_shelves": 20,
        "shelf_blocklist_version": SHELF_RULES_VERSION,
    }
    json.dumps(summary)  # must not raise (plain ints, not numpy ints)


def test_missing_column_raises_clear_error():
    with pytest.raises(ValueError, match="description"):
        add_quality_flags(_books().drop(columns="description"))


def test_empty_frame():
    out, summary = add_quality_flags(_books().iloc[0:0])
    assert len(out) == 0
    assert summary["n_books"] == 0
    assert out["has_description"].dtype == bool


def test_parquet_round_trip(tmp_path):
    out, _ = add_quality_flags(_books())
    path = tmp_path / "books.parquet"
    out.to_parquet(path, index=False)
    back = pd.read_parquet(path)
    assert back["has_description"].dtype == bool
    assert back["description_issue"].fillna("ok").tolist() == [
        "ok", "too_short", "missing", "missing"
    ]
    assert [list(x) for x in back["shelves"]] == [["heist"], ["fantasy"], [], []]


# ------------------------------------------------- follow-up fixes (Oct 13)


def test_custom_shelves_col_writes_contract_columns():
    raw = _books().rename(columns={"shelves": "popular_shelves", "description": "desc_raw"})
    out, _ = add_quality_flags(raw, shelves_col="popular_shelves", description_col="desc_raw")
    assert out["shelves"].tolist() == [["heist"], ["fantasy"], [], []]
    assert out["description"].iloc[0] == "A crew of con artists plans an impossible robbery."
    # the raw source columns are left untouched for the caller to drop
    pd.testing.assert_series_equal(out["popular_shelves"], raw["popular_shelves"])
    pd.testing.assert_series_equal(out["desc_raw"], raw["desc_raw"])


def test_json_string_shelves_are_parsed():
    as_json = json.dumps([{"name": "heist", "count": "10"}, {"name": "to-read", "count": "99"}])
    assert clean_shelves(as_json) == ["heist"]


def test_python_repr_string_shelves_are_parsed():
    as_repr = "[{'name': 'heist', 'count': '10'}, {'name': 'favorites', 'count': '50'}]"
    assert clean_shelves(as_repr) == ["heist"]


def test_plain_string_shelf_is_still_one_name():
    assert clean_shelves("fantasy") == ["fantasy"]


def test_bare_string_inside_record_list_is_unknown_not_infinite():
    books = _books().iloc[:1].copy()
    books["shelves"] = [[{"name": "heist", "count": "10"}, "romance"]]
    out, summary = add_quality_flags(books)
    assert out["shelves"].iloc[0] == ["heist"]
    assert summary["n_unknown_shelf_entries"] == 1
